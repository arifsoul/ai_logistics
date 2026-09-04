import NavBar from "@/components/NavBar";

/** Shared shell for the authenticated pages. NavBar also gates on the token. */
export default function AppLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <>
      <NavBar />
      {children}
    </>
  );
}
