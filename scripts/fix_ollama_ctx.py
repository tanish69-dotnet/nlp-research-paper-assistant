path = r'C:\Users\Tanish\nlp\app\models\ollama.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and replace the block from line 60 to 77 (0-indexed: 59-76)
new_lines = []
skip_until = -1
for i, line in enumerate(lines):
    if skip_until > 0 and i < skip_until:
        continue
    skip_until = -1

    # Line 60 (0-indexed 59): has_images = ...
    if 'has_images = any(bool(message.images)' in line:
        indent = '        '
        new_lines.append(indent + 'has_images = any(bool(message.images) for message in request.messages)\n')
        new_lines.append(indent + 'options: dict[str, Any] = {}\n')
        new_lines.append(indent + '# Always set num_ctx so prompts larger than Ollama default 4096\n')
        new_lines.append(indent + '# are not rejected with HTTP 400.\n')
        new_lines.append(indent + 'options["num_ctx"] = 8192\n')
        new_lines.append(indent + 'if request.temperature is not None:\n')
        new_lines.append(indent + '    options["temperature"] = request.temperature\n')
        new_lines.append(indent + 'if request.max_tokens is not None:\n')
        new_lines.append(indent + '    options["num_predict"] = request.max_tokens\n')
        new_lines.append('\n')
        new_lines.append(indent + 'payload: dict[str, Any] = {\n')
        new_lines.append(indent + '    "model": request.model,\n')
        new_lines.append(indent + '    "messages": messages,\n')
        new_lines.append(indent + '    "stream": False,\n')
        new_lines.append(indent + '    "options": options,\n')
        new_lines.append(indent + '}\n')
        # Skip old lines until "if request.response_format"
        for j in range(i + 1, len(lines)):
            if 'if request.response_format' in lines[j]:
                skip_until = j
                break
        continue
    new_lines.append(line)

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f'Done. Total lines: {len(new_lines)}')

