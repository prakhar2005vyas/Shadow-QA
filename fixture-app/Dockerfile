FROM nginx:1.27-alpine

# Copy static files
COPY . /usr/share/nginx/html/

# Custom nginx config: serve static files, return 404 for missing pages
# (this is what makes the dead links actually 404, not a redirect)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
