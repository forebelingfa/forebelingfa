// Usage: frida -D <device-id> -N com.limoolive.stream -l hook_goog.js

setImmediate(function () {
  Java.perform(function () {
    const AUTH_PATH = '/api/go_v3/limoo/google_auth';

    function log(message) {
      console.log('[TAMIL] ' + message);
    }

    function extractAuthResult(response) {
      try {
        const body = response.peekBody(1024 * 1024).string();
        const parsed = JSON.parse(body);
        const data = parsed && parsed.data;
        if (!data || typeof data !== 'object') {
          log('Google auth response did not contain an object in data');
          return;
        }

        const jwt = data.jwt_authorization_token || data.jwt_token || data.jwt;
        const token = data.token || data.ws_token;
        if (!jwt || !token) {
          log('Google auth response did not contain both session tokens (code=' + parsed.code + ')');
          return;
        }

        console.log('AUTH_TOKENS:' + JSON.stringify({
          jwt: String(jwt),
          token: String(token),
          user_id: String(data.user_id || data.userId || ''),
        }));
      } catch (error) {
        log('Unable to parse Google auth response: ' + error);
      }
    }

    try {
      const RealCall = Java.use('okhttp3.internal.connection.RealCall');
      const getResponse = RealCall['getResponseWithInterceptorChain$okhttp'].overload();

      getResponse.implementation = function () {
        const request = this.request();
        const path = request.url().encodedPath();
        log(request.method() + ' ' + request.url().host() + path);

        const response = getResponse.call(this);
        if (path.indexOf(AUTH_PATH) !== -1) {
          extractAuthResult(response);
        }
        return response;
      };

      log('Monitoring OkHttp requests and Tamil Google-auth responses');
    } catch (error) {
      log('Failed to hook OkHttp response processing: ' + error);
      throw error;
    }
  });
});
