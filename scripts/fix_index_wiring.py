import sys

path = r'C:\Users\Tanish\nlp\app\static\index.html'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Update goToSection & hero buttons
old_nav = '''function goToSection(id) {
  const target = $(id);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
}
$("hero-ask-btn").addEventListener("click", () => { $("query").focus(); goToSection("section-ask"); });
$("hero-upload-btn").addEventListener("click", () => goToSection("section-papers"));'''

new_nav = '''function goToSection(id) {
  const map = {
    "section-ask": "ask-lens",
    "section-papers": "papers-lens",
    "section-evidence": "evidence-lens",
    "section-history": "history-lens"
  };
  const targetId = map[id] || id;
  const target = $(targetId);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
}
if ($("hero-ask-btn")) $("hero-ask-btn").addEventListener("click", () => { $("query").focus(); goToSection("ask-lens"); });
if ($("hero-upload-btn")) $("hero-upload-btn").addEventListener("click", () => goToSection("papers-lens"));'''

if old_nav in text:
    text = text.replace(old_nav, new_nav)
    print("Replaced old_nav (LF)")
elif old_nav.replace('\n', '\r\n') in text:
    text = text.replace(old_nav.replace('\n', '\r\n'), new_nav.replace('\n', '\r\n'))
    print("Replaced old_nav (CRLF)")
else:
    print("Warning: old_nav not found")

# 2. Update dropzone and upload handling
old_upload = '''const dropZone = $("drop-zone");
["dragenter", "dragover"].forEach((evt) => dropZone.addEventListener(evt, (evt2) => { evt2.preventDefault(); dropZone.classList.add("dragging"); }));
["dragleave", "drop"].forEach((evt) => dropZone.addEventListener(evt, (evt2) => { evt2.preventDefault(); dropZone.classList.remove("dragging"); }));
dropZone.addEventListener("drop", (evt) => {
  const files = evt.dataTransfer && evt.dataTransfer.files;
  if (!files || !files.length) return;
  try { $("pdf").files = files; } catch (e) { return; }
  showFileName();
});
$("pdf").addEventListener("change", showFileName);

function showFileName() {
  const node = $("file-name");
  const file = $("pdf").files[0];
  if (!file) { setHtml(node, "No file selected"); node.classList.remove("has-file"); return; }
  setHtml(node, "Selected: " + file.name + " (" + (file.size / (1024 * 1024)).toFixed(1) + " MiB)");
  node.classList.add("has-file");
}

async function uploadPdf() {
  const box = $("upload-result");
  box.replaceChildren();
  const file = $("pdf").files[0];'''

new_upload = '''let currentSelectedFile = null;

function updateSelectedFile(file) {
  currentSelectedFile = file;
  const node = $("file-name");
  if (!node) return;
  if (!file) {
    setHtml(node, "No file selected");
    node.style.color = "#c9a24a";
    node.classList.remove("has-file");
    return;
  }
  setHtml(node, "✓ Ready to index: " + file.name + " (" + (file.size / (1024 * 1024)).toFixed(2) + " MiB)");
  node.style.color = "#4ade80";
  node.classList.add("has-file");
}

const dropZone = $("drop-zone");
if (dropZone) {
  ["dragenter", "dragover"].forEach((evt) => dropZone.addEventListener(evt, (evt2) => { evt2.preventDefault(); dropZone.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach((evt) => dropZone.addEventListener(evt, (evt2) => { evt2.preventDefault(); dropZone.classList.remove("dragging"); }));
  dropZone.addEventListener("drop", (evt) => {
    const files = evt.dataTransfer && evt.dataTransfer.files;
    if (!files || !files.length) return;
    updateSelectedFile(files[0]);
    try {
      const dt = new DataTransfer();
      dt.items.add(files[0]);
      if ($("pdf")) $("pdf").files = dt.files;
    } catch (e) {}
  });
  dropZone.addEventListener("click", (evt) => {
    if (evt.target !== $("pdf") && $("pdf")) {
      $("pdf").click();
    }
  });
}

if ($("pdf")) {
  $("pdf").addEventListener("change", () => {
    const file = $("pdf").files && $("pdf").files[0];
    updateSelectedFile(file);
  });
}

async function uploadPdf() {
  const box = $("upload-result");
  box.replaceChildren();
  const file = currentSelectedFile || ($("pdf") && $("pdf").files && $("pdf").files[0]);'''

if old_upload in text:
    text = text.replace(old_upload, new_upload)
    print("Replaced old_upload (LF)")
elif old_upload.replace('\n', '\r\n') in text:
    text = text.replace(old_upload.replace('\n', '\r\n'), new_upload.replace('\n', '\r\n'))
    print("Replaced old_upload (CRLF)")
else:
    print("Warning: old_upload not found")

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Finished successfully")

