#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/HUD.h"
#include "GameFramework/GameModeBase.h"
#include "RoadScenes.generated.h"

class UCameraComponent;
class UMaterialInstanceDynamic;
class FJsonObject;

UCLASS()
class ROADSCENES_API ARoadScene : public AActor
{
    GENERATED_BODY()
public:
    ARoadScene();
    bool Select(int32 Index);
    void CycleSignal();
    void ResetView();
    int32 Current = -1;
    int32 Signal = 0;
    FString Title;
    FString Error;
    FVector StartPosition;
    float StartYaw = 0;
    float CameraHeight = 15;
    float CameraPitch = -8;
    float CameraFOV = 66;
    float Speed = 35;
    float TurnRate = 65;
    FVector2D RoomMin, RoomMax;
    bool HasSignal = false;
private:
    UPROPERTY() TArray<UActorComponent*> Geometry;
    UPROPERTY() TArray<UMaterialInstanceDynamic*> SignalMaterials;
    UPROPERTY() TArray<AActor*> Lights;
    UPROPERTY() TArray<UMaterialInterface*> Materials;
    void ClearScene();
    void UpdateSignal();
};

UCLASS()
class ROADSCENES_API ARoadPawn : public APawn
{
    GENERATED_BODY()
public:
    ARoadPawn();
    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;
    UPROPERTY() UCameraComponent* Camera;
    UPROPERTY() ARoadScene* Scene;
    bool TopView = false;
    bool InputReady = false;
    void ResetView();
};

UCLASS()
class ROADSCENES_API ARoadHUD : public AHUD
{
    GENERATED_BODY()
public:
    virtual void DrawHUD() override;
    virtual void NotifyHitBoxClick(FName BoxName) override;
};

UCLASS()
class ROADSCENES_API ARoadGameMode : public AGameModeBase
{
    GENERATED_BODY()
public:
    ARoadGameMode();
};
