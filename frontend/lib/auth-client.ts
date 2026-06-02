"use client";

import { createAuthClient } from "better-auth/react";

// baseURL omitted → uses the current window origin, so it works on localhost and any
// tunnel host. basePath matches the server (/auth).
export const authClient = createAuthClient({ basePath: "/auth" });

export const { signIn, signOut, useSession } = authClient;
