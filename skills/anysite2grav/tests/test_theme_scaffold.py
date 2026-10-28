"""Run with GRAV_TEST_ROOT=/path/to/grav python3 -m unittest discover -s <this-dir> -v.

Requires PHP 8.3+ on PATH and an installed Grav 2 runtime. All writes use temporary roots.
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
RUNTIME = Path(os.environ.get("GRAV_TEST_ROOT", "/nonexistent"))


@unittest.skipUnless((RUNTIME / "vendor/autoload.php").exists(), "set GRAV_TEST_ROOT to an installed Grav 2 runtime")
class ThemeScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="grav-theme-test-")
        self.addCleanup(self.workspace.cleanup)
        self.project = Path(self.workspace.name)
        self.grav = self.project / "grav"
        self.grav.mkdir()
        for entry in ("vendor", "system", "index.php"):
            (self.grav / entry).symlink_to(RUNTIME / entry, target_is_directory=(RUNTIME / entry).is_dir())
        (self.grav / "user/config").mkdir(parents=True)
        (self.grav / "user/config/site.yaml").write_text('title: Fixture\n')
        self.migration = self.project / "migration"
        self.migration.mkdir()
        (self.migration / "routes.json").write_text(json.dumps({"source": "https://example.com", "pages": []}))
        self.theme = self.grav / "user/themes/fixture"
        self.scaffold()

    def scaffold(self, *arguments):
        result = subprocess.run([
            sys.executable, str(SCRIPTS / "scaffold_theme.py"), str(self.migration),
            "--grav", str(self.grav), "--name", "fixture", "--fonts", "skip", *arguments,
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def config(self, relative):
        result = subprocess.run(["php", str(SCRIPTS / "grav_config.php"), str(self.grav), "get", relative], check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_rerun_preserves_editorial_values_and_project_files(self):
        settings = self.grav / "user/config/themes/fixture.yaml"
        settings.write_text('logo: media://edited.svg\nnoindex_hosts: []\nanalytics:\n  enabled: false\n  hosts: []\nnavigation:\n  en:\n    main: []\n')
        custom_css = self.theme / "css/custom.css"
        custom_css.write_text('.project { color: red; }\n')
        blueprint = self.theme / "blueprints.yaml"
        blueprint.write_text('name: Edited blueprint\n')
        self.scaffold("--force")
        config = self.config("user/config/themes/fixture.yaml")
        self.assertEqual(config["logo"], "media://edited.svg")
        self.assertEqual(config["noindex_hosts"], [])
        self.assertEqual(config["navigation"]["en"]["main"], [])
        self.assertIs(config["analytics"]["enabled"], False)
        self.assertEqual(config["analytics"]["hosts"], [])
        self.assertIn("ga4_via_gtm", config["analytics"])
        self.assertEqual(custom_css.read_text(), '.project { color: red; }\n')
        self.assertEqual(blueprint.read_text(), 'name: Edited blueprint\n')

    def test_reset_and_template_replacement_are_explicit(self):
        settings = self.grav / "user/config/themes/fixture.yaml"
        settings.write_text('editor_marker: keep\n')
        (self.theme / "css/custom.css").write_text('edited')
        self.scaffold("--force-templates")
        self.assertEqual(self.config("user/config/themes/fixture.yaml")["editor_marker"], "keep")
        self.assertNotEqual((self.theme / "css/custom.css").read_text(), 'edited')
        self.scaffold("--force", "--reset-config")
        self.assertNotIn("editor_marker", self.config("user/config/themes/fixture.yaml"))

    def test_tailwind_mode_keeps_overrides(self):
        (self.theme / "css/custom.css").write_text('.project { color: red; }\n')
        self.scaffold("--force", "--tailwind", "--no-build")
        package = json.loads((self.theme / "package.json").read_text())
        self.assertIn("tailwindcss", package["devDependencies"])
        self.assertEqual((self.theme / "css/custom.css").read_text(), '.project { color: red; }\n')

    def test_render_collects_late_assets_once_and_preserves_navigation(self):
        (self.grav / "user/plugins").symlink_to(RUNTIME / "user/plugins", target_is_directory=True)
        for directory in ("cache", "logs", "tmp", "backup", "images", "assets", "user/accounts", "user/data"):
            (self.grav / directory).mkdir()
        for plugin in ("admin2", "api"):
            directory = self.grav / "user/config/plugins"
            directory.mkdir(exist_ok=True)
            (directory / f"{plugin}.yaml").write_text('enabled: false\n')
        (self.grav / "user/config/system.yaml").write_text('pages:\n  theme: fixture\ncache:\n  enabled: true\ndebugger:\n  enabled: false\n')
        (self.grav / "user/config/themes/fixture.yaml").write_text('''noindex_hosts: [127.0.0.1]
shared_form_routes: [/forms/contact]
analytics:
  enabled: false
navigation:
  en:
    main:
      - label: Parent
        url: /
        children:
          - label: Child
            url: /child
''')
        home = self.grav / "user/pages/01.home"
        home.mkdir(parents=True)
        (home / "fixture.md").write_text('---\ntitle: Fixture\n---\nFixture body\n')
        form_directory = self.grav / "user/pages/02.forms/contact"
        form_directory.mkdir(parents=True)
        (form_directory / "form.md").write_text('''---
title: Contact
form:
  name: contact
  action: /forms/contact
  xhr_submit: true
  fields:
    email:
      type: email
      label: Email
    captcha:
      type: cap
  buttons:
    submit:
      type: submit
      value: Send
---
''')
        (self.theme / "templates/fixture.html.twig").write_text('''{% extends 'partials/base.html.twig' %}
{% block javascripts %}{{ parent() }}{% do assets.addInlineJs('window.childScript = true;', {group: 'bottom'}) %}{% endblock %}
{% block content %}
  {% do assets.addInlineCss('.late-module { color: red; }') %}
  {% do assets.addInlineJs('window.lateHead = true;') %}
  {% do assets.addInlineJsModule('window.lateModule = true;') %}
  <p>Late registration fixture</p>
  {% include 'partials/form-embed.html.twig' with {name: 'contact'} %}
{% endblock %}
''')
        blueprint_check = self.project / "blueprints.php"
        blueprint_check.write_text('''<?php
$loader = require getcwd() . '/vendor/autoload.php';
$grav = \\Grav\\Common\\Grav::instance(['loader' => $loader]);
$grav->setup();
$grav->initializeCli();
$grav['themes']->init();
$blueprints = new \\Grav\\Common\\Data\\Blueprints('blueprints://pages');
$resolved = [];
foreach (['sections', 'modular', 'form'] as $pageType) {
    $resolved[$pageType] = $blueprints->get($pageType)->toArray();
}
echo json_encode($resolved, JSON_THROW_ON_ERROR);
''')
        result = subprocess.run(["php", str(blueprint_check)], cwd=self.grav, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        resolved = json.loads(result.stdout)
        for page_type, blueprint in resolved.items():
            fields = blueprint["form"]["fields"]["tabs"]["fields"]["content"]["fields"]
            self.assertIn("header.head_title", fields, page_type)
            self.assertIn("header.body_classes", fields, page_type)
            self.assertIn("header.noindex", fields, page_type)
        modular_fields = resolved["modular"]["form"]["fields"]["tabs"]["fields"]["content"]["fields"]
        self.assertIn("header.content.items", modular_fields)
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        server_log = tempfile.TemporaryFile()
        self.addCleanup(server_log.close)
        server = subprocess.Popen(["php", "-S", f"127.0.0.1:{port}", "system/router.php"], cwd=self.grav, stdout=server_log, stderr=server_log)
        def stop_server():
            server.terminate()
            server.wait(timeout=10)
        self.addCleanup(stop_server)
        for attempt in range(30):
            try:
                with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                    rendered = response.read().decode()
                    self.assertIn('noindex', response.headers.get('X-Robots-Tag', ''))
                break
            except HTTPError as error:
                self.fail(error.read().decode() + '\n' + '\n'.join(path.read_text() for path in (self.grav / 'logs').glob('*.log')))
            except URLError:
                if server.poll() is not None or attempt == 29:
                    server_log.seek(0)
                    self.fail(server_log.read().decode())
                time.sleep(0.1)
        for cache_state in ("cold", "warm"):
            with self.subTest(cache=cache_state):
                if cache_state == "warm":
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                        rendered = response.read().decode()
                head = rendered.split('</head>')[0]
                for marker in ('.late-module', 'window.lateHead', 'window.lateModule'):
                    self.assertEqual(head.count(marker), 1, rendered)
                self.assertEqual(rendered.count('window.childScript'), 1)
                self.assertEqual(rendered.count('/js/site.js'), 1)
                self.assertLess(head.index('/css/site.css'), head.index('/css/custom.css'))
                self.assertIn('href="/" aria-current="page">Parent</a>', rendered)
                self.assertIn('aria-label="Submenu: Parent"', rendered)
                self.assertIn('data-form="contact"', rendered)
                self.assertIn('name="data[email]"', rendered)
                self.assertEqual(rendered.count('/captcha/cap-handler.js'), 1)
                self.assertEqual(rendered.count('/captcha/cap/cap.min.js'), 1)
                self.assertEqual(rendered.count('/xhr-submitter.js'), 1)
        artifact_directory = os.environ.get("GRAV_TEST_ARTIFACTS")
        if artifact_directory:
            artifacts = Path(artifact_directory)
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / "rendered.html").write_text(rendered)
            (artifacts / "site.css").write_text((self.theme / "css/site.css").read_text())
            (artifacts / "site.js").write_text((self.theme / "js/site.js").read_text())


if __name__ == "__main__":
    unittest.main()
