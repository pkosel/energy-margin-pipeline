{
  # Host-side tooling only: linters, psql, just. The pipeline itself (Airflow,
  # dbt) runs in containers, so this shell does not have to match their
  # Python version.
  description = "Energy margin pipeline development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };

        python = pkgs.python312;
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # psql client, matching the warehouse server version.
            postgresql_16

            python
            uv

            # pre-commit runs these as `language: system`, so they must be here.
            ruff
            sqlfluff
            yamllint
            pre-commit

            just
          ];

          shellHook = ''
            # Pin uv to the Nix interpreter; downloaded CPython builds are not
            # patched for NixOS.
            export UV_PYTHON=${python}/bin/python3.12
            export UV_PYTHON_DOWNLOADS=never

            echo "energy-margin-pipeline"
            echo "  python  $(python3 --version | cut -d' ' -f2)"
            echo "  uv      $(uv --version | cut -d' ' -f2)"
            echo "  psql    $(psql --version | cut -d' ' -f3)"
            echo "  just    $(just --version | cut -d' ' -f2)"
            echo ""
            echo "dbt and airflow run in containers. See 'just --list'"
          '';
        };
      }
    );
}
