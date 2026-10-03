import { useEffect, useRef } from "react";

const CLIENT_ID = "566577575077-2n0jo8rp263fltulupcfrvelg04mcjkg.apps.googleusercontent.com";

// Renders Google's own "Sign in with Google" button via Identity Services
// (loaded in index.html). `onCredential` receives the signed ID token JWT;
// the parent decides what to do with it (call loginWithGoogle, navigate,
// resume a pending cart/wishlist action, show an error) -- this component
// only renders the button and hands back the token.
export default function GoogleSignInButton({ onCredential, onError, text = "continue_with" }) {
  const divRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    function render() {
      if (cancelled || !divRef.current || !window.google?.accounts?.id) return;
      window.google.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: (response) => {
          if (response?.credential) onCredential(response.credential);
          else onError?.(new Error("Google sign-in did not return a credential"));
        },
      });
      window.google.accounts.id.renderButton(divRef.current, {
        theme: "outline",
        size: "large",
        width: 320,
        text,
      });
    }

    if (window.google?.accounts?.id) {
      render();
    } else {
      // The GIS script tag is `async defer` in index.html, so it may not
      // have loaded yet on first mount -- poll briefly rather than assuming
      // a fixed delay.
      const interval = setInterval(() => {
        if (window.google?.accounts?.id) {
          clearInterval(interval);
          render();
        }
      }, 200);
      return () => {
        cancelled = true;
        clearInterval(interval);
      };
    }
    return () => {
      cancelled = true;
    };
  }, [onCredential, onError, text]);

  return <div ref={divRef} style={{ display: "flex", justifyContent: "center" }} />;
}
