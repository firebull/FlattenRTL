import time

from main import main
from rich import print

if __name__ == "__main__":
    start = time.time()
    main()
    end = time.time()
    print(f"[green]INFO[/green] Total flattering time: {(end - start):.2f} seconds")