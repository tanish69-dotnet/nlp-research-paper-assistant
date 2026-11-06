path = r'C:\Users\Tanish\nlp\app\static\index.html'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

bad = '''  if () .value = paper.paper_id;
  if () .value = paper.paper_id;'''

good = '''  if ($("scope")) $("scope").value = paper.paper_id;
  if ($("evidence-scope")) $("evidence-scope").value = paper.paper_id;'''

if bad in text:
    text = text.replace(bad, good)
    print("Fixed bad syntax!")
else:
    print("bad not found directly, checking variations")
    import re
    text = re.sub(r'if \(\) \.value = paper\.paper_id;\s*if \(\) \.value = paper\.paper_id;', good, text)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")

