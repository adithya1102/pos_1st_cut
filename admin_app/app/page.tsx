import { redirect } from "next/navigation";

export default function Home() {
  // The dashboard layout does the real auth check; unauthenticated users get
  // bounced from there to /login.
  redirect("/dashboard");
}
