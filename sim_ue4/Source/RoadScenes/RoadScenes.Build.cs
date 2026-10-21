using UnrealBuildTool;
public class RoadScenes : ModuleRules
{
    public RoadScenes(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new string[] {
            "Core", "CoreUObject", "Engine", "InputCore", "Json", "ProceduralMeshComponent"
        });
    }
}
