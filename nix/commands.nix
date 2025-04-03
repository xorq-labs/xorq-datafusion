{ pkgs, python }:
let

  git-bin = "${pkgs.git}/bin/git";

  xorq-kill-lsof-grep-port = pkgs.writeShellScriptBin "xorq-kill-lsof-grep-port" ''
    set -eux

    port=$1
    pids=($(lsof -i4@localhost | grep "$port" | awk '{print $2}'))
    if [ "''${#pids[@]}" -ne "0" ]; then
      kill "''${pids[@]}"
    fi
  '';

  xorq-gh-config-set-browser-false = pkgs.writeShellScriptBin "xorq-gh-config-set-browser-false" ''
    ${pkgs.gh}/bin/gh config set browser false
  '';

  xorq-fmt = pkgs.writeShellScriptBin "xorq-fmt" ''
    set -eux

    ${python}/bin/python -m black .
    ${python}/bin/python -m blackdoc .
    ${python}/bin/python -m ruff --fix .
  '';

  xorq-lint = pkgs.writeShellScriptBin "xorq-lint" ''
    set -eux

    ${python}/bin/python -m black --quiet --check .
    ${python}/bin/python -m ruff .
  '';

  xorq-download-data = pkgs.writeShellScriptBin "xorq-download-data" ''
    set -eux

    owner=''${1:-ibis-project}
    repo=''${1:-testing-data}
    rev=''${1:-master}

    repo_dir=$(${git-bin} rev-parse --show-toplevel)

    outdir=$repo_dir/ci/ibis-testing-data
    rm -rf "$outdir"
    url="https://github.com/$owner/$repo"

    args=("$url")
    if [ "$rev" = "master" ]; then
        args+=("--depth" "1")
    fi

    args+=("$outdir")
    ${git-bin} clone "''${args[@]}"

    if [ "$rev" != "master" ]; then
        ${git-bin} -C "''${outdir}" checkout "$rev"
    fi
  '';

  xorq-ensure-download-data = pkgs.writeShellScriptBin "xorq-ensure-download-data" ''
    repo_dir=$(${git-bin} rev-parse --show-toplevel)
    if [ ! -d "$repo_dir/ci/ibis-testing-data" ]; then
      ${xorq-download-data}/bin/xorq-download-data
    fi
  '';

  xorq-docker-compose-up = pkgs.writeShellScriptBin "xorq-docker-compose-up" ''
    set -eux

    backends=''${@}
    ${pkgs.docker-compose}/bin/docker-compose up --build --wait ''${backends[@]}
  '';

  xorq-newgrp-docker-compose-up = pkgs.writeShellScriptBin "xorq-newgrp-docker-compose-up" ''
    set -eux

    newgrp docker <<<"${xorq-docker-compose-up}/bin/xorq-docker-compose-up ''${@}"
  '';

  xorq-git-fetch-origin-pull = pkgs.writeShellScriptBin "xorq-git-fetch-origin-pull" ''
    set -eux

    PR=$1
    branchname="origin-pr-$PR"
    ${git-bin} fetch origin pull/$PR/head:$branchname
  '';

  xorq-git-config-blame-ignore-revs = pkgs.writeShellScriptBin "xorq-git-config-blame-ignore-revs" ''
    set -eux

    # https://black.readthedocs.io/en/stable/guides/introducing_black_to_your_project.html#avoiding-ruining-git-blame
    ignore_revs_file=''${1:-.git-blame-ignore-revs}
    ${git-bin} config blame.ignoreRevsFile "$ignore_revs_file"
  '';

  xorq-maturin-build = pkgs.writeShellScriptBin "xorq-maturin-build" ''
    set -eux
    repo_dir=$(${git-bin} rev-parse --show-toplevel)
    cd "$repo_dir"
    ${python}/bin/maturin build --release
  '';

  xorq-commands = {
    inherit
      xorq-kill-lsof-grep-port
      xorq-fmt
      xorq-lint
      xorq-ensure-download-data
      xorq-docker-compose-up
      xorq-newgrp-docker-compose-up
      xorq-git-fetch-origin-pull
      xorq-git-config-blame-ignore-revs
      xorq-maturin-build
      xorq-gh-config-set-browser-false
      ;
  };

  xorq-commands-star = pkgs.buildEnv {
    name = "xorq-commands-star";
    paths = builtins.attrValues xorq-commands;
  };
in
{
  inherit xorq-commands xorq-commands-star;
}
