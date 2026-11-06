"""Identificação da distribuição, sem inicialização do motor de revisão."""

import argparse
from importlib.metadata import version


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Contract Analyzer Enterprise: bootstrap do pacote Python.'
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {version("contract-analyzer-enterprise")}',
    )
    parser.parse_args()
    parser.print_help()


if __name__ == '__main__':
    main()
