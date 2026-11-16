"""Менеджер состояний FSM для мессенджера Макс."""

from typing import Any, Optional


class StateManager:
    """Управление состояниями пользователей в памяти."""

    def __init__(self):
        # user_id -> {"state": str | None, "data": dict}
        self._states: dict[int, dict[str, Any]] = {}

    def get_user_state(self, user_id: int) -> Optional[str]:
        """Получить текущее имя состояния пользователя."""
        return self._states.get(user_id, {}).get("state")

    def get_data(self, user_id: int) -> dict[str, Any]:
        """Получить данные состояния пользователя."""
        return self._states.get(user_id, {}).get("data", {})

    def set_state(self, user_id: int, state: Optional[str], **kwargs) -> None:
        """Установить состояние пользователя."""
        if user_id not in self._states:
            self._states[user_id] = {"state": state, "data": {}}
        else:
            self._states[user_id]["state"] = state
        if kwargs:
            self._states[user_id]["data"].update(kwargs)

    def update_data(self, user_id: int, **kwargs) -> None:
        """Обновить данные состояния."""
        if user_id not in self._states:
            self._states[user_id] = {"state": None, "data": {}}
        self._states[user_id]["data"].update(kwargs)

    def clear_state(self, user_id: int) -> None:
        """Сбросить состояние (сохраняя кэш последнего поиска)."""
        if user_id in self._states:
            last_search = self._states[user_id]["data"].get("last_search")
            self._states[user_id]["state"] = None
            self._states[user_id]["data"] = {"last_search": last_search} if last_search else {}


# Предопределенные константы состояний
STATE_SEARCH_INPUT = "search_input"
STATE_DATE_INPUT = "date_input"
