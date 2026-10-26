# Book Agent frontend

React-интерфейс учебного Book Agent. Agent loop, tool policy и состояние run
остаются на FastAPI backend; frontend отображает их через HTTP DTO.

Общее описание проекта, backend и evals — в [корневом README](../README.md).

## Запуск

Требуется Node.js 22.x. Тесты проверены на Node 22.22.2. На Node 26.11 они
падают из-за ограничения jsdom на opaque origin; `build` и `lint` при этом
работают.

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
