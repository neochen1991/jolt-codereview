export type RegistrationAccountType = "user" | "project_admin";

export function registrationGlobalRole(value: unknown, userCount: number) {
  if (userCount === 0) return "root";
  const accountType = String(value || "user");
  if (accountType !== "user" && accountType !== "project_admin") {
    throw new Error("account_type must be user or project_admin");
  }
  return accountType;
}

export function canCreateProjectForGlobalRole(value: unknown) {
  return value === "root" || value === "project_admin";
}
