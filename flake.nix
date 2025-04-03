{
  description = "A modern data processing library focused on composability, portability, and performance.";

  inputs = {
    flake-utils.url = "github:numtide/flake-utils";
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs = {
        pyproject-nix.follows = "pyproject-nix";
        uv2nix.follows = "uv2nix";
        nixpkgs.follows = "nixpkgs";
      };
    };
    rust-overlay.url = "github:oxalica/rust-overlay";
    nix-utils = {
      url = "github:xorq-labs/nix-utils";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      rust-overlay,
      nix-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pythonDarwinHotfix = old: {
          # https://github.com/NixOS/nixpkgs/pull/390454
          preConfigure = old.preConfigure + (
            pkgs.lib.optionalString
            (system == "aarch64-darwin")
            ''
              # Fix _ctypes module compilation
              export NIX_CFLAGS_COMPILE+=" -DUSING_APPLE_OS_LIBFFI=1"
            ''
          );
        };
        pkgs = import nixpkgs {
          inherit system;
          overlays = [
            (import rust-overlay)
            (_final: prev: {
              python310 = prev.python310.overrideAttrs pythonDarwinHotfix;
              python311 = prev.python311.overrideAttrs pythonDarwinHotfix;
            })
          ];
        };
        inherit (nix-utils.lib.${system}.utils) drvToApp;

        src = ./.;
        mk-xorq-datafusion = import ./nix/xorq-datafusion.nix {
          inherit
            pkgs
            pyproject-nix
            uv2nix
            pyproject-build-systems
            src
            ;
        };
        xorq-datafusion-310 = mk-xorq-datafusion pkgs.python310;
        xorq-datafusion-311 = mk-xorq-datafusion pkgs.python311;
        xorq-datafusion-312 = mk-xorq-datafusion pkgs.python312;
      in
      {
        formatter = pkgs.nixfmt-rfc-style;
        apps = {
          ipython-310 = drvToApp {
            drv = xorq-datafusion-310.virtualenv;
            name = "ipython";
          };
          ipython-311 = drvToApp {
            drv = xorq-datafusion-311.virtualenv;
            name = "ipython";
          };
          ipython-312 = drvToApp {
            drv = xorq-datafusion-312.virtualenv;
            name = "ipython";
          };
          default = self.apps.${system}.ipython-310;
        };
        lib = {
          inherit
            pkgs
            mk-xorq-datafusion
            xorq-datafusion-310
            xorq-datafusion-311
            xorq-datafusion-312
            ;
        };
        devShells = {
          impure = pkgs.mkShell {
            packages = [
              pkgs.python310
              pkgs.uv
              xorq-datafusion-310.toolchain
              pkgs.gh
            ];
            shellHook = ''
              unset PYTHONPATH
            '';
          };
          virtualenv-310 = xorq-datafusion-310.shell;
          virtualenv-311 = xorq-datafusion-311.shell;
          virtualenv-312 = xorq-datafusion-312.shell;
          default = self.devShells.${system}.virtualenv-310;
        };
      }
    );
}
