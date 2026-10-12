#!/usr/bin/env python3
import sys

def main():
    city = sys.argv[1] if len(sys.argv) > 1 else "Beijing"
    print(f"Weather report for {city}: Sunny, 22°C")

if __name__ == "__main__":
    main()
