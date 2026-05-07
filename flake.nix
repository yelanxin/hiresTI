{
  description = "HiresTI — High-Res TIDAL player for Linux with bit-perfect playback";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          pygobject3
          pycairo
          pyopengl
          requests
          urllib3
          tidalapi
          pillow
          qrcode
          python-dateutil
          typing-extensions
          isodate
          mpegdash
          pyaes
          ratelimit
          six
          certifi
          setproctitle
          pystray
        ]);

        rustPlatform = pkgs.rustPlatform;
        version = builtins.replaceStrings [ "\n" ] [ "" ]
          (builtins.readFile ./version.txt);

        rustAudioCore = rustPlatform.buildRustPackage {
          pname = "rust_audio_core";
          inherit version;
          src = ./src_rust/rust_audio_core;
          cargoLock = {
            lockFile = ./src_rust/rust_audio_core/Cargo.lock;
          };
          # The in-tree .cargo/config.toml pins crates-io to a local
          # `vendor/` dir for the offline Docker / AUR builds; Nix has
          # its own vendor handling via cargoLock, so wipe the override
          # before the build phase.
          postPatch = ''
            rm -f .cargo/config.toml
          '';
          nativeBuildInputs = with pkgs; [ pkg-config cmake ];
          buildInputs = with pkgs; [ alsa-lib libusb1 openssl ];
          doCheck = false;
        };

        rustVizCore = rustPlatform.buildRustPackage {
          pname = "viz_core";
          inherit version;
          src = ./src_rust/rust_viz_core;
          cargoLock = {
            lockFile = ./src_rust/rust_viz_core/Cargo.lock;
          };
          doCheck = false;
        };

        desktopFile = pkgs.writeText "com.hiresti.player.desktop" ''
          [Desktop Entry]
          Name=HiresTI
          Comment=High-Res TIDAL player for Linux
          Exec=hiresti
          Icon=hiresti
          Terminal=false
          Type=Application
          Categories=AudioVideo;Audio;Player;Music;
          StartupWMClass=HiresTI
        '';

        runtimeLibs = with pkgs; [
          gtk4
          libadwaita
          gtksourceview5
          webkitgtk_6_0
          graphene
          harfbuzz
          pango
          cairo
          gdk-pixbuf
          glib
          gobject-introspection
          glib-networking
          # GStreamer kept only for GstPbutils.Discoverer (URI probing in
          # src/_rust/audio.py); the audio playback path itself no longer
          # uses GStreamer.
          gst_all_1.gstreamer
          gst_all_1.gst-plugins-base
          alsa-lib
          libpulseaudio
          pipewire
          libusb1
          mesa
          libglvnd
        ];

        hiresti = pkgs.stdenv.mkDerivation {
          pname = "hiresti";
          inherit version;

          src = ./.;

          nativeBuildInputs = with pkgs; [
            wrapGAppsHook4
            gobject-introspection
            makeWrapper
          ];

          buildInputs = runtimeLibs ++ [ pythonEnv ];

          dontBuild = true;

          installPhase = ''
            runHook preInstall

            mkdir -p $out/share/hiresti
            cp -r src         $out/share/hiresti/src
            cp version.txt    $out/share/hiresti/
            if [ -f LICENSE ]; then cp LICENSE $out/share/hiresti/; fi
            cp -r icons       $out/share/hiresti/

            install -Dm755 ${rustAudioCore}/lib/librust_audio_core.so \
              $out/share/hiresti/src_rust/rust_audio_core/target/release/librust_audio_core.so
            install -Dm755 ${rustVizCore}/lib/libviz_core.so \
              $out/share/hiresti/src_rust/rust_viz_core/target/release/libviz_core.so

            install -Dm644 ${desktopFile} \
              $out/share/applications/com.hiresti.player.desktop

            install -d $out/share/icons
            cp -r icons/hicolor $out/share/icons/

            mkdir -p $out/bin
            makeWrapper ${pythonEnv}/bin/python3 $out/bin/hiresti \
              --add-flags "$out/share/hiresti/src/main.py" \
              --set PYTHONDONTWRITEBYTECODE 1 \
              --prefix LD_LIBRARY_PATH : "${pkgs.lib.makeLibraryPath runtimeLibs}" \
              --prefix GI_TYPELIB_PATH : "${pkgs.lib.makeSearchPathOutput "lib" "lib/girepository-1.0" runtimeLibs}" \
              --chdir $out/share/hiresti

            runHook postInstall
          '';

          meta = with pkgs.lib; {
            description = "High-Res TIDAL player for Linux with bit-perfect playback";
            homepage = "https://github.com/yelanxin/hiresTI";
            license = licenses.gpl3Plus;
            platforms = platforms.linux;
            mainProgram = "hiresti";
          };
        };
      in {
        packages = {
          default = hiresti;
          inherit hiresti;
          rust_audio_core = rustAudioCore;
          viz_core = rustVizCore;
        };

        apps.default = {
          type = "app";
          program = "${hiresti}/bin/hiresti";
        };

        devShells.default = pkgs.mkShell {
          inputsFrom = [ hiresti ];
          packages = with pkgs; [
            cargo
            rustc
            clippy
            rustfmt
            pkg-config
          ];
        };
      });
}
