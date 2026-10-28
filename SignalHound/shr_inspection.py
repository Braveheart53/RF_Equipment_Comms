from shr_parser import ShrFileParser
from pprint import pprint

file_path = r"C:\Measurements\recording.shr"

with ShrFileParser(file_path) as parser:
    sweeps = parser.get_all_sweeps()

print("Returned object type:", type(sweeps))
print("Object structure:")
if hasattr(sweeps, "shape"):
    print("Shape:", sweeps.shape)
if hasattr(sweeps, "dtype"):
    print("Data type:", sweeps.dtype)

try:
    print("Number of returned items:", len(sweeps))
    print("\nFirst returned item:")
    pprint(sweeps[0])
except (TypeError, KeyError, IndexError):
    pprint(sweeps)