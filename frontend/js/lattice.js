/* lattice.js — the Lattice decomposition canvas as a Synapse tab.

   The canvas (frontend/lattice.html) is a complete self-contained page with
   its own design system (vellum/ink, not the Mainframe theme), so it is
   embedded in an iframe rather than restyled into a view. It persists itself
   through /api/synapse/lattice; this file is only the mounting point. */
(function () {
  window.Views = window.Views || {};
  window.Views.lattice = {
    id: "lattice", label: "Lattice", scoped: false,
    render(host) {
      host.innerHTML = "";
      const frame = document.createElement("iframe");
      frame.src = "/lattice.html";
      frame.title = "Lattice";
      // .view gives 22px padding inside the 100vh-52px layout; fill the rest.
      frame.style.cssText =
        "width:100%;height:calc(100vh - 96px);border:1px solid var(--border);" +
        "border-radius:8px;background:#E9EBE4;display:block";
      host.appendChild(frame);
    },
  };
})();
