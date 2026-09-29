"""A few calls, printed. Run: python examples/demo.py"""

import tfstdlib

print(tfstdlib.call("cidrsubnets", "10.0.0.0/16", 4, 4, 8))
print(tfstdlib.call("split", ",", "a,b,,c"))
print(tfstdlib.call("regexall", "x*", "abxd"))
print(tfstdlib.call("formatdate", "EEEE, DD MMM YYYY", "2024-05-17T13:04:05Z"))
print(tfstdlib.evaluate('{for k, v in {a = 1, b = 2} : upper(k) => v * 10}'))
print(tfstdlib.call("yamlencode", {"name": "x", "ports": (80, 443)}), end="")
