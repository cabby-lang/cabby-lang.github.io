// The Cabby website: copy buttons, heading links and the contents menu on
// small screens. Everything works without it.

document.addEventListener("DOMContentLoaded", () => {
	// Copy buttons. Code is copied with its tabs, which Cabby needs.
	for (const pre of document.querySelectorAll("pre.code")) {
		const button = document.createElement("button");
		button.className = "copy";
		button.type = "button";
		button.textContent = "Copy";
		button.addEventListener("click", async () => {
			const text = pre.querySelector("code").textContent;
			try {
				await navigator.clipboard.writeText(text);
				button.textContent = "Copied";
				button.classList.add("done");
			} catch {
				button.textContent = "Select and copy";
			}
			setTimeout(() => { button.textContent = "Copy"; button.classList.remove("done"); }, 1600);
		});
		pre.appendChild(button);
	}

	// "Try it" on whole programs, when the playground can run them: those
	// with a main that don't use a library needing the computer itself.
	if (document.body.dataset.playground) {
		// (what wasm/README.md says a browser hasn't, and what the docs' examples showed it can't: a C
		// function of the program's own, a header beside it, MIME types, zlib, printf)
		const needsComputer = /^(use (local|gui|gtk|game|tgame|world|tui|sound|videos|media|speech|printing|bluetooth|dbus|desktop|screens|mouse|keyboard|brightness|volume|power|networks|emails|processes|shell|threads|databases|secrets|system|users|mime|archives|standard|events|os|linux)\b|extern\b|\s*\.\.\.\s*$)/m;
		for (const pre of document.querySelectorAll("pre.code.cabby")) {
			const text = pre.querySelector("code").textContent;
			if (!/^int main\b/m.test(text) || needsComputer.test(text)) continue;
			let b = "";
			for (const byte of new TextEncoder().encode(text.replace(/\n*$/, "\n"))) b += String.fromCharCode(byte);
			const a = document.createElement("a");
			a.className = "try";
			a.href = "/playground/#code=" + btoa(b).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
			a.textContent = "Try it";
			pre.appendChild(a);
		}
	}

	// A # link beside each heading, to link straight to it.
	for (const h of document.querySelectorAll(".prose :is(h2, h3, h4)[id]")) {
		const a = document.createElement("a");
		a.className = "anchor";
		a.href = "#" + h.id;
		a.setAttribute("aria-label", "Link to this section");
		a.textContent = "#";
		h.appendChild(a);
	}

	// The sidebar becomes a menu on small screens.
	const sidebar = document.querySelector(".sidebar");
	const toggle = document.querySelector(".menu-toggle");
	if (sidebar && toggle) {
		toggle.hidden = false;
		toggle.addEventListener("click", () => {
			const open = document.body.classList.toggle("menu-open");
			toggle.setAttribute("aria-expanded", open);
		});
		sidebar.addEventListener("click", (e) => {
			if (e.target.closest("a")) {
				document.body.classList.remove("menu-open");
				toggle.setAttribute("aria-expanded", "false");
			}
		});
		const current = sidebar.querySelector("[aria-current]");
		if (current) sidebar.scrollTop = current.offsetTop - sidebar.clientHeight / 2;
	}
});
