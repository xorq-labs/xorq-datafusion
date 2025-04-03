{
  pkgs,
  pyproject-nix,
  uv2nix,
  pyproject-build-systems,
  src,
}:
let
  mk-xorq-datafusion =
    python:
    let
      inherit (pkgs.lib) nameValuePair;
      inherit (pkgs.lib.path) append;
      compose = pkgs.lib.trivial.flip pkgs.lib.trivial.pipe;
      addNativeBuildInputs =
        drvs:
        (old: {
          nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ drvs;
        });
      addResolved =
        final: names:
        (old: {
          nativeBuildInputs =
            (old.nativeBuildInputs or [ ])
            ++ final.resolveBuildSystem (
              pkgs.lib.listToAttrs (map (name: pkgs.lib.nameValuePair name [ ]) names)
            );
        });
      darwinPyprojectOverrides = final: prev: {
        scipy = prev.scipy.overrideAttrs (compose [
          (addResolved final [
            "meson-python"
            "ninja"
            "cython"
            "numpy"
            "pybind11"
            "pythran"
          ])
          (addNativeBuildInputs [
            pkgs.gfortran
            pkgs.cmake
            pkgs.xsimd
            pkgs.pkg-config
            pkgs.openblas
            pkgs.meson
          ])
        ]);
        xgboost = prev.xgboost.overrideAttrs (compose [
          (addNativeBuildInputs [ pkgs.cmake ])
          (addResolved final [ "hatchling" ])
        ]);
        scikit-learn = prev.scikit-learn.overrideAttrs (
          addResolved final [
            "meson-python"
            "ninja"
            "cython"
            "numpy"
            "scipy"
          ]
        );
        duckdb = prev.duckdb.overrideAttrs (addResolved final [
          "setuptools"
          "pybind11"
        ]);
        pyarrow = prev.pyarrow.overrideAttrs (compose [
          (addNativeBuildInputs [
            pkgs.cmake
            pkgs.pkg-config
            pkgs.arrow-cpp
          ])
          (addResolved final [
            "numpy"
            "cython"
            "setuptools"
          ])
        ]);
        google-crc32c = prev.google-crc32c.overrideAttrs (addResolved final [ "setuptools" ]);
        psycopg2-binary = prev.psycopg2-binary.overrideAttrs (compose [
          (addResolved final [
            "setuptools"
          ])
          (addNativeBuildInputs [
            pkgs.postgresql
            pkgs.openssl
          ])
        ]);
      };
      toolchain = pkgs.rust-bin.fromRustupToolchainFile (append src "rust-toolchain.toml");
      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = src; };
      wheelOverlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };
      pyprojectOverrides-base = final: prev: {
        cityhash = prev.cityhash.overrideAttrs (
          addResolved final (if python.pythonAtLeast "3.12" then [ "setuptools" ] else [ ])
        );
      };
      xorq-datafusion-maturinBuildOverride = _final: prev: {
        xorq-datafusion = prev.xorq-datafusion.overrideAttrs (old: {
          nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
            toolchain
            pkgs.rustPlatform.maturinBuildHook
            pkgs.rustPlatform.cargoSetupHook
          ];
          cargoDeps = pkgs.rustPlatform.importCargoLock {
            lockFile = "${old.src}/Cargo.lock";
          };
        });
      };
      pythonSet-base =
        # Use base package set from pyproject.nix builders
        (pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        }).overrideScope
          (
            pkgs.lib.composeManyExtensions (
              [
                pyproject-build-systems.overlays.default
                wheelOverlay
                pyprojectOverrides-base
                xorq-datafusion-maturinBuildOverride
              ]
              ++ pkgs.lib.optionals pkgs.stdenv.isDarwin [ darwinPyprojectOverrides ]
            )
          );
      overridePythonSet =
        overrides: pythonSet-base.overrideScope (pkgs.lib.composeManyExtensions overrides);
      virtualenv = pythonSet-base.mkVirtualEnv "xorq" workspace.deps.all;

      inherit
        (import ./commands.nix {
          inherit pkgs;
          python = virtualenv;
        })
        xorq-commands-star
        ;
      toolsPackages = [
        pkgs.uv
        toolchain
        xorq-commands-star
        pkgs.gh
      ];
      shell = pkgs.mkShell {
        packages = [
          virtualenv
        ] ++ toolsPackages;
        shellHook = ''
          unset PYTHONPATH
        '';
      };

    in
    {
      inherit
        pythonSet-base
        virtualenv
        toolchain
        xorq-commands-star
        toolsPackages
        shell
        ;
    };
in
mk-xorq-datafusion
