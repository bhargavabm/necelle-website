(function () {
  "use strict";

  const navItems = [
    { label: "Home", href: "index.html" },
    { label: "Simulation", href: "simulation.html" },
    { label: "Architecture", href: "about.html#architecture" },
    { label: "About", href: "about.html" },
    { label: "Contact", href: "about.html#contact" },
    { label: "Privacy", href: "privacy.html" },
    { label: "Terms", href: "terms.html" }
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
    const link = document.createElement("a");
    link.href = item.href;
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

  const form = document.getElementById("contact-form");
  if (!form) return;

  const error = document.getElementById("contact-error");
  const nameInput = document.getElementById("contact-name");
  const emailInput = document.getElementById("contact-email");
  const messageInput = document.getElementById("contact-message");

  function showError(text) {
    error.textContent = text;
    error.hidden = false;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    error.hidden = true;

    const name = nameInput.value.trim();
    const email = emailInput.value.trim();
    const message = messageInput.value.trim();

    if (name.length === 0) {
      showError("Enter your name.");
      return;
    }
    if (email.length === 0) {
      showError("Enter your email.");
      return;
    }
    if (!email.includes("@")) {
      showError("Enter a valid email with @.");
      return;
    }
    if (message.length === 0) {
      showError("Enter your message.");
      return;
    }

    const subject = "Nacelle project enquiry";
    const body = "Name: " + name + "\nEmail: " + email + "\n\n" + message;
    const href = "mailto:bhargavabm2007@gmail.com?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);
    const link = document.createElement("a");
    link.href = href;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    link.remove();
  });
})();
