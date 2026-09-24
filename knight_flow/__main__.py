import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()

from .app import main


if __name__ == "__main__":
    main()
