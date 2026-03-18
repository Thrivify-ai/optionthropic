import { useEffect } from "react";
import { useRouter } from "next/router";
import { isAuthenticated } from "../lib/auth";

export default function Index() {
  const router = useRouter();
  useEffect(() => {
    router.replace(isAuthenticated() ? "/dashboard" : "/login");
  }, []);
  return null;
}
