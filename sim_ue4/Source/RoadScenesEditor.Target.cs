using UnrealBuildTool;
using System.Collections.Generic;
public class RoadScenesEditorTarget : TargetRules
{
    public RoadScenesEditorTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.V2;
        ExtraModuleNames.Add("RoadScenes");
    }
}
