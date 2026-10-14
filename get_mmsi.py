import re


def get_mmsi_list(filepath="whale_watch_boats.txt"):
    with open(filepath, "r") as f:
        text = f.read()
        mmsis = re.findall(r"MMSI:\s*(\d+)", text)
        return [int(mmsi) for mmsi in mmsis]


if __name__ == "__main__":
    mmsi_list = get_mmsi_list()
    print(mmsi_list)
