# Sony SRD Native API (not included)

This folder is intentionally empty in the public repository.

Sony's Spatial Reality Display Native API headers and libraries are **not**
redistributed here (`Sony CONFIDENTIAL` / do not redistribute without
permission).

## Download

1. Open the Sony developer download page:  
   https://xyn.sony.net/en/developer/setup/spatial-reality-display/download-info
2. Under **For Application Developers**, download **Native API**
   (`NativeAPI-2.5.0.zip` or newer).
3. Extract the archive. Inside you will find an `XR_API` directory (headers +
   `xr_api.lib`), typically under something like:

   ```text
   XR_API_XX/XR_API/
   ```

4. Copy that **`XR_API`** folder so this repository looks like:

   ```text
   SpatialReality/
     XR_API/
       include/
         xr_api_wrapper.h
         …
       lib/
         Release/xr_api.lib
         Debug/xr_api.lib
       bin/          # optional — runtime DLLs if present in your package
         Release/…
   ```

5. Build the bridge:

   ```bat
   python scripts/build_dll.py
   ```

   or:

   ```bat
   cmake -B build -G "Visual Studio 17 2022" -A x64
   cmake --build build --config Release
   ```

The Python package looks for `build/Release/SRDBridge.dll` (and will offer to
build it if missing).
