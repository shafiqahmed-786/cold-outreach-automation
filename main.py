"""
Entry point for the cold outreach pipeline.

Run:
    python main.py --domain stripe.com          # live mode
    python main.py --domain stripe.com --mock   # mock mode (no API credits)
    python main.py --domain stripe.com --reset  # clear cached state
    python main.py --domain stripe.com --yes    # skip email confirmation
    python main.py --help                       # full usage
"""

from cli import run

if __name__ == "__main__":
    run()