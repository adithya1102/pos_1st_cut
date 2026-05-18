"use client";

import { signIn, useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, Suspense } from "react";

function Spinner() {
  return (
    <div className="flex h-screen w-full items-center justify-center bg-[#0f172a]">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-[#f97316] border-r-transparent" />
    </div>
  );
}

function LoginContent() {
  const { status } = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") || "/";

  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [otpStep, setOtpStep] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (status === "authenticated") {
      router.replace(callbackUrl);
    }
  }, [status, router, callbackUrl]);

  if (status === "loading" || status === "authenticated") {
    return <Spinner />;
  }

  const handleSendOtp = (e: React.FormEvent) => {
    e.preventDefault();
    if (!phone.trim()) {
      setError("Please enter a valid mobile number.");
      return;
    }
    setError("");
    setOtpStep(true);
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    const result = await signIn("credentials", {
      phone,
      otp,
      redirect: false,
    });
    setLoading(false);
    if (result?.error) {
      setError("Invalid OTP. Please try again.");
    } else {
      router.replace(callbackUrl);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#0f172a] px-4">
      <div className="w-full max-w-sm space-y-8">

        {/* Branding */}
        <div className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-[#f97316] shadow-lg shadow-orange-900/40">
            <span className="text-3xl font-black text-white">G</span>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-[#f8fafc]">
            Gusto
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Sign in to browse the menu &amp; place your order
          </p>
        </div>

        {/* Card */}
        <div className="space-y-5 rounded-2xl bg-[#1e293b] p-8 shadow-2xl ring-1 ring-slate-700/50">

          {/* Google */}
          <button
            onClick={() => signIn("google", { callbackUrl })}
            className="flex w-full items-center justify-center gap-3 rounded-xl border border-slate-600 bg-[#0f172a] px-6 py-3.5 text-sm font-semibold text-[#f8fafc] transition-all duration-200 hover:border-[#f97316] hover:bg-[#1a2332] active:scale-[0.97]"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" aria-hidden="true">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
            </svg>
            Continue with Google
          </button>

          {/* Divider */}
          <div className="flex items-center gap-3">
            <div className="h-px flex-1 bg-slate-700" />
            <span className="text-xs text-slate-500">or</span>
            <div className="h-px flex-1 bg-slate-700" />
          </div>

          {/* Mobile OTP — Step 1: phone input */}
          {!otpStep ? (
            <form onSubmit={handleSendOtp} className="space-y-3">
              <input
                type="tel"
                value={phone}
                onChange={(e) => { setPhone(e.target.value); setError(""); }}
                placeholder="Mobile number"
                className="w-full rounded-xl border border-slate-600 bg-[#0f172a] px-4 py-3 text-sm text-[#f8fafc] placeholder-slate-500 outline-none transition-colors focus:border-[#f97316] focus:ring-1 focus:ring-[#f97316]"
              />
              {error && <p className="text-xs text-red-400">{error}</p>}
              <button
                type="submit"
                className="w-full rounded-xl bg-[#f97316] px-6 py-3.5 text-sm font-semibold text-white transition-all duration-200 hover:bg-[#ea6a05] active:scale-[0.97]"
              >
                Send OTP
              </button>
            </form>
          ) : (
            /* Mobile OTP — Step 2: OTP entry */
            <form onSubmit={handleVerify} className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm text-slate-400">
                  OTP sent to{" "}
                  <span className="font-medium text-[#f8fafc]">{phone}</span>
                </p>
                <button
                  type="button"
                  onClick={() => { setOtpStep(false); setOtp(""); setError(""); }}
                  className="text-xs text-[#f97316] hover:underline"
                >
                  Change
                </button>
              </div>
              <input
                type="text"
                inputMode="numeric"
                value={otp}
                onChange={(e) => { setOtp(e.target.value.replace(/\D/g, "").slice(0, 6)); setError(""); }}
                placeholder="• • • • • •"
                maxLength={6}
                className="w-full rounded-xl border border-slate-600 bg-[#0f172a] px-4 py-3 text-center text-lg font-bold tracking-[0.5em] text-[#f8fafc] placeholder-slate-600 outline-none transition-colors focus:border-[#f97316] focus:ring-1 focus:ring-[#f97316]"
              />
              {error && <p className="text-xs text-red-400">{error}</p>}
              <button
                type="submit"
                disabled={loading || otp.length < 6}
                className="w-full rounded-xl bg-[#f97316] px-6 py-3.5 text-sm font-semibold text-white transition-all duration-200 hover:bg-[#ea6a05] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-r-transparent" />
                    Verifying…
                  </span>
                ) : (
                  "Verify & Login"
                )}
              </button>
            </form>
          )}

          <p className="text-center text-xs leading-relaxed text-slate-500">
            By continuing you agree to our&nbsp;
            <span className="text-slate-400">Terms of Service</span>
            &nbsp;&amp;&nbsp;
            <span className="text-slate-400">Privacy Policy</span>.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <LoginContent />
    </Suspense>
  );
}
