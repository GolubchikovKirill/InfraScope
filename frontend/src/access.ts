export const HONEST_SIGN_OPERATOR_EMAIL = "golubchikovka@regstaer.ru";

export function canAccessHonestSign(user: { email?: string | null } | null | undefined) {
  return user?.email?.trim().toLocaleLowerCase("ru-RU") === HONEST_SIGN_OPERATOR_EMAIL;
}
