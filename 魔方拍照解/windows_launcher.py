import os

from server import main


if __name__ == "__main__":
    no_browser = os.environ.get("CUBE_NO_BROWSER", "").strip().lower() in {"1", "true", "yes"}
    main(open_browser=not no_browser)
