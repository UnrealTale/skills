# ==============================================================================
# Capability Preset [fonts_theme]: Cross-Distro Desktop Fonts, Icons & GTK/Qt Themes
# ==============================================================================
bwrap_setup_fonts_and_theme() {
  [[ "${ENABLE_FONTS_THEME:-true}" != "true" ]] && return 0

  bwrap_ro_bind_try /usr/share/fonts /usr/share/fonts
  bwrap_ro_bind_try /usr/local/share/fonts /usr/local/share/fonts
  bwrap_ro_bind_try /etc/fonts /etc/fonts
  bwrap_ro_bind_try "${HOME}/.local/share/fonts" "${HOME}/.local/share/fonts"
  bwrap_ro_bind_try "${HOME}/.cache/fontconfig" "${HOME}/.cache/fontconfig"
  bwrap_ro_bind_try /var/cache/fontconfig /var/cache/fontconfig
  bwrap_ro_bind_try /usr/share/icons /usr/share/icons
  bwrap_ro_bind_try /usr/share/themes /usr/share/themes
}
