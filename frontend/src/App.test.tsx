import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { AgentRunResponse } from './api/types'

const COMPLETED_RUN: AgentRunResponse = {
  id: 'c79f4bf2-448d-4eab-aa02-cfefac2f1f51',
  status: 'completed',
  final_answer: 'Нашёл «Дюну» Фрэнка Герберта.',
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Book Agent chat', () => {
  it('sends a message and renders the completed run', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(COMPLETED_RUN), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), 'Найди Дюну')
    await user.click(screen.getByRole('button', { name: 'Отправить' }))

    expect(await screen.findByText('Нашёл «Дюну» Фрэнка Герберта.')).toBeVisible()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/agent/runs',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ message: 'Найди Дюну' }),
      }),
    )
  })

  it('leaves loading and shows a safe error when the API is unavailable', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('offline'))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), 'Покажи библиотеку')
    await user.click(screen.getByRole('button', { name: 'Отправить' }))

    expect(
      await screen.findByText(
        'Не удалось связаться с сервером. Проверьте, запущен ли backend.',
      ),
    ).toBeVisible()
    await user.type(screen.getByLabelText('Сообщение агенту'), 'Повторить')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Отправить' })).toBeEnabled()
    })
    expect(screen.queryByText('Выполняю запрос')).not.toBeInTheDocument()
  })

  it('does not expose backend details from an HTTP error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'internal database failure' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), 'Покажи библиотеку')
    await user.click(screen.getByRole('button', { name: 'Отправить' }))

    expect(
      await screen.findByText(
        'Сервер не смог обработать запрос. Попробуйте ещё раз.',
      ),
    ).toBeVisible()
    expect(screen.queryByText('internal database failure')).not.toBeInTheDocument()
  })

  it('does not send an empty message', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), '   ')

    expect(screen.getByRole('button', { name: 'Отправить' })).toBeDisabled()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
