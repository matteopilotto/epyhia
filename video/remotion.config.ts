import { Config } from "@remotion/cli/config";

// Rendering is local and spends nothing, so it does not route through the Action Gate
// (DESIGN.md 6.4). Publishing the result does.
Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
