(function () {
  "use strict";

  const navItems = [
    { label: "Home", href: "index.html" },
    { label: "Simulation", href: "simulation.html" },
    { label: "Architecture", href: "about.html#architecture" },
    { label: "About", href: "about.html" },
    { label: "Privacy", href: "privacy.html" },
    { label: "Terms", dialog: true }
  ];

  const nav = document.getElementById("site-nav");
  if (!nav) return;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "menu-button";
  button.textContent = "Menu";
  button.setAttribute("aria-label", "Toggle navigation");
  button.setAttribute("aria-controls", "primary-nav-list");
  button.setAttribute("aria-expanded", "false");

  const list = document.createElement("ul");
  list.className = "nav-list";
  list.id = "primary-nav-list";

  navItems.forEach(function (item) {
    const itemElement = document.createElement("li");
    const link = document.createElement(item.dialog ? "button" : "a");
    if (item.dialog) {
      link.type = "button";
      link.className = "nav-dialog-button";
      link.setAttribute("data-terms-open", "");
      link.setAttribute("aria-haspopup", "dialog");
    } else {
      link.href = item.href;
    }
    link.textContent = item.label;
    itemElement.appendChild(link);
    list.appendChild(itemElement);
  });

  nav.appendChild(button);
  nav.appendChild(list);

  function closeMenu() {
    list.classList.remove("is-open");
    button.setAttribute("aria-expanded", "false");
  }

  button.addEventListener("click", function () {
    const isOpen = list.classList.toggle("is-open");
    button.setAttribute("aria-expanded", String(isOpen));
  });

  list.addEventListener("click", function (event) {
    if (event.target.closest("a")) closeMenu();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeMenu();
  });

  window.addEventListener("resize", function () {
    if (window.innerWidth >= 768) closeMenu();
  });

  function updateActiveLink() {
    const currentPage = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();
    const currentHash = window.location.hash;
    const links = list.querySelectorAll("a");

    links.forEach(function (link) {
      const url = new URL(link.href, window.location.href);
      const linkPage = url.pathname.split("/").pop().toLowerCase();
      let isActive = linkPage === currentPage;

      if (isActive && (link.hash.length > 0 || currentHash.length > 0)) {
        isActive = link.hash === currentHash;
      }

      if (isActive) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  updateActiveLink();
  window.addEventListener("hashchange", updateActiveLink);
})();

(function () {
  "use strict";

  const dialog = document.getElementById("terms-dialog");
  if (!dialog) return;

  let opener = null;

  document.querySelectorAll("[data-terms-open]").forEach(function (button) {
    button.addEventListener("click", function () {
      opener = button;
      dialog.showModal();
    });
  });

  const closeButton = dialog.querySelector("[data-terms-close]");
  if (closeButton) {
    closeButton.addEventListener("click", function () {
      dialog.close();
    });
  }

  dialog.addEventListener("close", function () {
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  });
})();
