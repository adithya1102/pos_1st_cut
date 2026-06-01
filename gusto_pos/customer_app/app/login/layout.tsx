import SessionProviderWrapper from "@/components/SessionProviderWrapper";

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return <SessionProviderWrapper>{children}</SessionProviderWrapper>;
}
