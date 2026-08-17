# Book Agent frontend

React-интерфейс учебного Book Agent. Agent loop, tool policy и состояние run
остаются на FastAPI backend; frontend отображает их через HTTP DTO.

## Запуск

Требуется Node.js 22.12 или новее.

```bash
npm install
npm run dev
```

Vite откроет приложение на `http://127.0.0.1:5173` и проксирует `/api` на
`http://127.0.0.1:8000`.

## Проверки

```bash
npm test
npm run build
npm run lint
```
