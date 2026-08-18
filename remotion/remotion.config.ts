import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
// The render host also runs LatentSync and Chatterbox on the GPU. Chrome tabs
// are CPU-bound here, so leave headroom rather than taking all 12 cores.
Config.setConcurrency(6);
Config.setChromiumOpenGlRenderer('angle-egl');
