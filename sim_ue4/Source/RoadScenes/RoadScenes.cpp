#include "RoadScenes.h"
#include "Modules/ModuleManager.h"
#include "ProceduralMeshComponent.h"
#include "Camera/CameraComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Engine/PointLight.h"
#include "Engine/SkyLight.h"
#include "Engine/Canvas.h"
#include "Engine/World.h"
#include "Engine/StaticMesh.h"
#include "GameFramework/PlayerController.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "InputCoreTypes.h"

IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, RoadScenes, "RoadScenes");

static FVector ReadVector(const TArray<TSharedPtr<FJsonValue>>& A)
{
    return FVector(A[0]->AsNumber(), A[1]->AsNumber(), A[2]->AsNumber());
}

ARoadScene::ARoadScene()
{
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
}

void ARoadScene::ClearScene()
{
    for (auto* C : Geometry) if (IsValid(C)) C->DestroyComponent();
    for (auto* L : Lights) if (IsValid(L)) L->Destroy();
    Geometry.Empty();
    Lights.Empty();
    SignalMaterials.Empty();
    Materials.Empty();
}

bool ARoadScene::Select(int32 Index)
{
    if (Index < 0 || Index > 2) return false;
    FString Text;
    const FString Path = FPaths::ProjectContentDir() / TEXT("Data") /
        FString::Printf(TEXT("scene_%d.json"), Index + 1);
    TSharedPtr<FJsonObject> Data;
    if (!FFileHelper::LoadFileToString(Text, *Path) ||
        !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Data) || !Data.IsValid())
    {
        Error = TEXT("Scene data missing. Run tools/generate_scenes.py.");
        UE_LOG(LogTemp, Error, TEXT("%s: %s"), *Error, *Path);
        return false;
    }
    // Validate generated data with tools/validate_scenes.py before launching.
    // Only clear the old scene after a new file has been loaded successfully.
    ClearScene();
    Error.Empty();
    Current = Index;
    Title = Data->GetStringField(TEXT("title"));
    StartPosition = ReadVector(Data->GetArrayField(TEXT("start")));
    StartYaw = Data->GetNumberField(TEXT("start_yaw"));
    const auto CameraData = Data->GetObjectField(TEXT("camera"));
    CameraHeight = CameraData->GetNumberField(TEXT("height_cm"));
    CameraPitch = CameraData->GetNumberField(TEXT("pitch_deg"));
    CameraFOV = CameraData->GetNumberField(TEXT("fov_deg"));
    Speed = Data->GetNumberField(TEXT("speed_cm_s"));
    TurnRate = Data->GetNumberField(TEXT("turn_deg_s"));
    const auto Bounds = Data->GetArrayField(TEXT("bounds"));
    RoomMin = FVector2D(Bounds[0]->AsNumber(), Bounds[1]->AsNumber());
    RoomMax = FVector2D(Bounds[2]->AsNumber(), Bounds[3]->AsNumber());
    HasSignal = Data->GetBoolField(TEXT("has_signal"));
    Signal = 0; // Every scene switch begins with a predictable RED state.

    for (const auto& Entry : Data->GetArrayField(TEXT("meshes")))
    {
        const auto MeshData = Entry->AsObject();
        auto* Mesh = NewObject<UProceduralMeshComponent>(this);
        AddInstanceComponent(Mesh);
        Mesh->SetupAttachment(RootComponent);
        Mesh->RegisterComponent();
        Geometry.Add(Mesh);
        TArray<FVector> V;
        TArray<FVector> N;
        TArray<FVector2D> UV;
        TArray<FLinearColor> Colors;
        TArray<int32> T;
        for (const auto& P : MeshData->GetArrayField(TEXT("vertices"))) V.Add(ReadVector(P->AsArray()));
        for (const auto& P : MeshData->GetArrayField(TEXT("normals"))) N.Add(ReadVector(P->AsArray()));
        for (const auto& P : MeshData->GetArrayField(TEXT("colors")))
        {
            const auto A = P->AsArray();
            Colors.Add(FLinearColor(A[0]->AsNumber(), A[1]->AsNumber(), A[2]->AsNumber(), 1));
        }
        for (const auto& P : MeshData->GetArrayField(TEXT("triangles"))) T.Add(P->AsNumber());
        for (const auto& P : V) UV.Add(FVector2D(P.X / 100, P.Y / 100));
        Mesh->CreateMeshSection_LinearColor(0, V, T, N, UV, Colors, TArray<FProcMeshTangent>(), false);
        Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
        const FString MatName = MeshData->GetStringField(TEXT("material"));
        const FString MatPath = TEXT("/Game/Materials/") + MatName + TEXT(".") + MatName;
        auto* Material = LoadObject<UMaterialInterface>(nullptr, *MatPath);
        if (Material) Mesh->SetMaterial(0, Material);
        else Error = TEXT("Materials missing. Run launch.ps1 -Prepare.");
    }

    if (HasSignal)
    {
        const FVector Base = ReadVector(Data->GetArrayField(TEXT("signal_position")));
        for (int32 I = 0; I < 3; ++I)
        {
            auto* Lamp = NewObject<UStaticMeshComponent>(this);
            AddInstanceComponent(Lamp);
            Lamp->SetupAttachment(RootComponent);
            Lamp->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Sphere.Sphere")));
            Lamp->RegisterComponent();
            Lamp->SetWorldLocation(Base + FVector(-6.5f, 0, 32 - I * 11));
            Lamp->SetWorldScale3D(FVector(0.035f, 0.085f, 0.085f));
            Lamp->SetCollisionEnabled(ECollisionEnabled::NoCollision);
            Geometry.Add(Lamp);
            auto* Master = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/Materials/M_Signal.M_Signal"));
            if (Master)
            {
                auto* MID = UMaterialInstanceDynamic::Create(Master, this);
                Lamp->SetMaterial(0, MID);
                SignalMaterials.Add(MID);
            }
        }
        UpdateSignal();
    }

    auto* Sky = GetWorld()->SpawnActor<ASkyLight>();
    Sky->GetLightComponent()->SetMobility(EComponentMobility::Movable);
    Sky->GetLightComponent()->SetIntensity(0.5f);
    Lights.Add(Sky);
    for (const auto& P : Data->GetArrayField(TEXT("lights")))
    {
        auto* Light = GetWorld()->SpawnActor<APointLight>();
        Light->SetActorLocation(ReadVector(P->AsArray()));
        auto* C = Cast<UPointLightComponent>(Light->GetLightComponent());
        C->SetMobility(EComponentMobility::Movable);
        C->SetIntensity(Data->GetNumberField(TEXT("light_intensity")));
        C->SetAttenuationRadius(1200);
        C->SetSourceRadius(35);
        Lights.Add(Light);
    }
    ResetView();
    return true;
}

void ARoadScene::UpdateSignal()
{
    const FLinearColor Colors[] = {FLinearColor(1, 0.015f, 0.005f),
        FLinearColor(1, 0.48f, 0.005f), FLinearColor(0.005f, 1, 0.035f)};
    for (int32 I = 0; I < SignalMaterials.Num(); ++I)
    {
        SignalMaterials[I]->SetVectorParameterValue(TEXT("Tint"), Colors[I]);
        SignalMaterials[I]->SetScalarParameterValue(TEXT("Glow"), I == Signal ? 5.0f : 0.02f);
    }
}

void ARoadScene::CycleSignal()
{
    if (!HasSignal) return;
    // Red -> green -> amber -> red.
    Signal = Signal == 0 ? 2 : (Signal == 2 ? 1 : 0);
    UpdateSignal();
}

void ARoadScene::ResetView()
{
    auto* PC = GetWorld()->GetFirstPlayerController();
    if (PC) if (auto* Pawn = Cast<ARoadPawn>(PC->GetPawn())) Pawn->ResetView();
}

ARoadPawn::ARoadPawn()
{
    PrimaryActorTick.bCanEverTick = true;
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
    Camera->SetupAttachment(RootComponent);
    AutoPossessPlayer = EAutoReceiveInput::Player0;
}

void ARoadPawn::BeginPlay()
{
    Super::BeginPlay();
    Scene = GetWorld()->SpawnActor<ARoadScene>();
    Scene->Select(0);
    // GameMode can possess the pawn after BeginPlay, so initialize the camera here
    // and configure controller input on the first possessed tick.
    ResetView();
}

void ARoadPawn::ResetView()
{
    if (!Scene) return;
    TopView = false;
    SetActorLocation(Scene->StartPosition);
    SetActorRotation(FRotator(0, Scene->StartYaw, 0));
    Camera->SetRelativeLocation(FVector(0, 0, Scene->CameraHeight));
    Camera->SetRelativeRotation(FRotator(Scene->CameraPitch, 0, 0));
    Camera->SetFieldOfView(Scene->CameraFOV);
}

void ARoadPawn::Tick(float DT)
{
    Super::Tick(DT);
    auto* PC = Cast<APlayerController>(GetController());
    if (!PC || !Scene) return;
    if (!InputReady)
    {
        PC->bShowMouseCursor = true;
        PC->bEnableClickEvents = true;
        PC->SetInputMode(FInputModeGameAndUI());
        InputReady = true;
    }
    if (PC->WasInputKeyJustPressed(EKeys::One)) Scene->Select(0);
    if (PC->WasInputKeyJustPressed(EKeys::Two)) Scene->Select(1);
    if (PC->WasInputKeyJustPressed(EKeys::Three)) Scene->Select(2);
    if (PC->WasInputKeyJustPressed(EKeys::R)) ResetView();
    if (PC->WasInputKeyJustPressed(EKeys::T)) Scene->CycleSignal();
    if (PC->WasInputKeyJustPressed(EKeys::C))
    {
        TopView = !TopView;
        if (TopView)
        {
            const FVector Center((Scene->RoomMin.X + Scene->RoomMax.X) / 2,
                (Scene->RoomMin.Y + Scene->RoomMax.Y) / 2, 1050);
            Camera->SetWorldLocation(Center);
            Camera->SetWorldRotation(FRotator(-90, 0, 0));
        }
        else
        {
            Camera->SetRelativeLocation(FVector(0, 0, Scene->CameraHeight));
            Camera->SetRelativeRotation(FRotator(Scene->CameraPitch, 0, 0));
        }
    }
    if (TopView || PC->IsInputKeyDown(EKeys::SpaceBar)) return;
    DT = FMath::Min(DT, 0.05f);
    const float Forward = float(PC->IsInputKeyDown(EKeys::W)) - float(PC->IsInputKeyDown(EKeys::S));
    const float Turn = float(PC->IsInputKeyDown(EKeys::D)) - float(PC->IsInputKeyDown(EKeys::A));
    AddActorWorldRotation(FRotator(0, Turn * Scene->TurnRate * DT, 0));
    FVector Next = GetActorLocation() + GetActorForwardVector() * Forward * Scene->Speed * DT;
    Next.X = FMath::Clamp(Next.X, Scene->RoomMin.X + 10, Scene->RoomMax.X - 10);
    Next.Y = FMath::Clamp(Next.Y, Scene->RoomMin.Y + 10, Scene->RoomMax.Y - 10);
    SetActorLocation(Next);
}

void ARoadHUD::DrawHUD()
{
    Super::DrawHUD();
    auto* Pawn = Cast<ARoadPawn>(GetOwningPawn());
    if (!Pawn || !Pawn->Scene) return;
    auto* S = Pawn->Scene;
    const TCHAR* Names[] = {TEXT("1  WOOD CURVE"), TEXT("2  GLOSS / REFLECTION"), TEXT("3  TRAFFIC LIGHT")};
    for (int32 I = 0; I < 3; ++I)
    {
        float X = 20 + I * 235;
        DrawRect(S->Current == I ? FLinearColor(0.04f, 0.35f, 0.3f, 0.95f) :
            FLinearColor(0.03f, 0.04f, 0.06f, 0.9f), X, 20, 225, 42);
        DrawText(Names[I], FLinearColor::White, X + 12, 32, nullptr, 1.1f);
        AddHitBox(FVector2D(X, 20), FVector2D(225, 42), FName(*FString::FromInt(I)), true);
    }
    DrawRect(FLinearColor(0.02f, 0.03f, 0.04f, 0.85f), 20, 72, 695, 98);
    DrawText(S->Title, FLinearColor::White, 32, 82);
    DrawText(TEXT("W/S move   A/D turn   SPACE hold   R reset   C overhead   T signal"),
        FLinearColor::White, 32, 107);
    DrawText(TEXT("PROTOTYPE | provisional dimensions | kinematic camera, no vehicle physics"),
        FLinearColor(1, 0.75f, 0.35f), 32, 132);
    if (S->HasSignal)
    {
        const TCHAR* State[] = {TEXT("RED"), TEXT("AMBER"), TEXT("GREEN")};
        DrawText(FString(TEXT("Signal: ")) + State[S->Signal], FLinearColor::White, 32, 185);
    }
    if (!S->Error.IsEmpty()) DrawText(S->Error, FLinearColor::Red, 32, 215);
}

void ARoadHUD::NotifyHitBoxClick(FName BoxName)
{
    auto* Pawn = Cast<ARoadPawn>(GetOwningPawn());
    if (Pawn && Pawn->Scene) Pawn->Scene->Select(FCString::Atoi(*BoxName.ToString()));
}

ARoadGameMode::ARoadGameMode()
{
    DefaultPawnClass = ARoadPawn::StaticClass();
    HUDClass = ARoadHUD::StaticClass();
}
