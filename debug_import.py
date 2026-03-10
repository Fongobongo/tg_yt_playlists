import sys
sys.path.insert(0, 'src')
with open('/tmp/debug_stage1.txt', 'w') as f:
    f.write('stage1: path set\n')
print("debug_import: path set", file=sys.stderr)
try:
    with open('/tmp/debug_stage2.txt', 'w') as f:
        f.write('stage2: about to import\n')
    import src.bot
    with open('/tmp/debug_stage3.txt', 'w') as f:
        f.write('stage3: imported\n')
    print("imported src.bot", file=sys.stderr)
    with open('/tmp/import_success.txt', 'w') as f:
        f.write('imported src.bot\n')
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    with open('/tmp/import_error.txt', 'w') as f:
        f.write(f"Error: {e}\n")
    with open('/tmp/import_traceback.txt', 'w') as f:
        f.write(traceback.format_exc())
