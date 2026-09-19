export const DESK_SESSION_KEY = "pronto-desk-session";

export function openDeskSession() {
  sessionStorage.setItem(DESK_SESSION_KEY, "1");
}
