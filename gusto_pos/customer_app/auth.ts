import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import Credentials from "next-auth/providers/credentials";

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET,
    }),
    Credentials({
      credentials: {
        phone: { label: "Phone", type: "text" },
        otp: { label: "OTP", type: "text" },
      },
      authorize(credentials) {
        if (credentials?.otp === "123456") {
          return {
            id: credentials.phone as string,
            name: "Mobile User",
          };
        }
        throw new Error("Invalid OTP");
      },
    }),
  ],
  pages: {
    signIn: "/login",
  },
});
