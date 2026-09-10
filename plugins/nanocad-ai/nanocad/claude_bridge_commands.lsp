;; Claude <-> nanoCAD bridge: user-facing helper commands.
;; Load once per session with (load "...claude_bridge_commands.lsp"),
;; or add to nanoCAD's Startup Suite to have it available automatically -
;; see the setup guide in this repo for exact steps.

(defun c:CLAUDESTATUS ( / )
  (princ "\n--- Claude <-> nanoCAD ---")
  (princ (strcat "\nnanoCAD: " (getvar "ACADVER")))
  (princ (strcat "\nDocument: " (getvar "DWGNAME")))
  (princ "\nCOM automation is ready whenever this document is open.")
  (princ "\nMake sure your Claude Code session has the nanocad-ai plugin loaded")
  (princ "\n(restart the session once after installing/updating it).")
  (princ "\n--------------------------")
  (princ)
)

(defun c:CLAUDEHELP ( / )
  (alert
    (strcat
      "Claude <-> nanoCAD\n\n"
      "1. Держите nanoCAD открытым с нужным документом.\n"
      "2. В Claude Code инструменты появляются после перезапуска сессии\n"
      "   (один раз после установки/обновления плагина nanocad-ai).\n"
      "3. Дальше просто просите Claude работать с чертежом как обычно.\n\n"
      "Команда CLAUDESTATUS выводит краткий статус в командную строку.\n"
      "Репозиторий: github.com/LectorNZ/nanocad-mcp-server"
    )
  )
  (princ)
)

(princ "\nClaude bridge commands loaded: CLAUDESTATUS, CLAUDEHELP")
(princ)
