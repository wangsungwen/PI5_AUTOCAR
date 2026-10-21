using UnrealBuildTool;
using System.Collections.Generic;
public class RoadScenesTarget : TargetRules
{
    public RoadScenesTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.V2;
        ExtraModuleNames.Add("RoadScenes");
    }
}
