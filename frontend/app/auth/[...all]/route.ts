import { toNextJsHandler } from "better-auth/next-js";
import { auth } from "@/lib/auth";

// better-auth's catch-all handler, mounted at /auth/* (basePath in lib/auth.ts).
export const { GET, POST } = toNextJsHandler(auth);
