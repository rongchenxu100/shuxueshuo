export const CURRENT_USER = {
  id: "user_haorong",
  slug: "haorong",
  displayName: "haorong",
  email: "ronghao@shuxueshuo.com",
} as const;

export function getCurrentUser() {
  return CURRENT_USER;
}

export function useCurrentUser() {
  return CURRENT_USER;
}
