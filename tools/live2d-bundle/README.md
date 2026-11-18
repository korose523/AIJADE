# Build the local Live2D adapter

Use the configured local package directory described in [Live2D setup](../../docs/LIVE2D-LOCAL.md). The build script reads existing tools and SDK files and writes the browser adapter and official shaders into that directory. It does not download dependencies or modify model files.

- Check out the [official Cubism Web Framework 5-r.5](https://github.com/Live2D/CubismWebFramework/tree/5-r.5) at commit `198a3769c26ca3d7b600e932590433badd392edd` in `framework-5-r.5/` under the local package directory.
- Install esbuild `0.25.12` under `vendor/build-tool/` in the same directory. Use the `node_modules/esbuild/bin/esbuild` entry shipped in the package.
- Use the matching [official hosted Cubism Core for Cubism 5.3](https://cubism.live2d.com/sdk-web/core/06/live2dcubismcore.min.js), subject to the [SDK agreements](https://www.live2d.com/en/sdk/download/web/), at `runtime/live2dcubismcore.min.js`. The local validation used SHA-256 `8741f739779b5d5210872bd3d7d99f0f1e56e6c87409e7d26d6bb4b80aa1ef47` and Core version `6.0.1`.

Run from the AIJADE checkout and pass the same absolute path used for `Live2D__Root`.

```sh
sh tools/live2d-bundle/build.sh /absolute/path/to/local-live2d-package
```
