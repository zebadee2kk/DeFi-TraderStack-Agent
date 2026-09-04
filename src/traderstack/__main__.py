"""``python -m traderstack`` runs the same guarded paper-trading entrypoint as
the ``traderstack-paper`` console script (see ``traderstack.cli``)."""

from traderstack.cli import main

if __name__ == "__main__":
    main()
