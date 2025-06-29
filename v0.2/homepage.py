
html = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Local MUD Terminal</title>
  <style>
    body { background-color: #000; color: #0f0; font-family: monospace; margin: 0; display: flex; flex-direction: column; height: 100vh; }
    #output { flex: 1; overflow-y: auto; padding: 10px; white-space: pre-wrap; }
    #input { border: none; padding: 10px; font-size: 1em; background: #111; color: #0f0; width: 100%; box-sizing: border-box; }
  </style>
</head>
<body>
  <div id=\"output\"></div>
  <input id=\"input\" type=\"text\" placeholder=\"Type your command...\" autofocus />
  <script>
    const ws = new WebSocket('ws://' + location.hostname + ':5000/ws');
    const output = document.getElementById('output');
    const input = document.getElementById('input');
    function print(message) {
      output.textContent += message + '\\n';
      output.scrollTop = output.scrollHeight;
    }
    ws.onopen = () => {
      console.log('[Connected to MUD]');
      const name = localStorage.getItem('player_name');
      if (name) ws.send(`__auth ${name}`);
    };
    ws.onmessage = (event) => {
      const data = event.data;
      print(data);
      if (data.toLowerCase().includes('enter your name')) {
        input.placeholder = "Enter your name...";
      }
    };
    ws.onclose = () => print('[Disconnected]');
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        const command = input.value.trim();
        if (command !== '') {
          print('> ' + command);
          ws.send(command);
          if (command.toLowerCase().startsWith('name ')) {
            const parts = command.split(' ');
            if (parts.length > 1) localStorage.setItem('player_name', parts[1]);
          }
          input.value = '';
        }
      }
    });
  </script>
</body>
</html>
"""