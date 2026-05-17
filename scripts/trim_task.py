import sys

path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

kept = lines[:128] + ['\n'] + lines[932:]

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(kept)

print(f'wrote {len(kept)} lines')
